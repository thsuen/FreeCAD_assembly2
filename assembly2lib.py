'''
assembly2 constraints are stored under App::FeaturePython object (constraintObj)

cName = findUnusedObjectName('axialConstraint')
c = FreeCAD.ActiveDocument.addObject("App::FeaturePython", cName)
c.addProperty("App::PropertyString","Type","ConstraintInfo","Object 1").Type = '...'
       
see http://www.freecadweb.org/wiki/index.php?title=Scripted_objects#Available_properties for more information
'''

import numpy, os
import FreeCAD
import FreeCADGui
import Part
from PySide import QtGui

__dir__ = os.path.dirname(__file__)
wb_globals = {}

def debugPrint( level, msg ):
    if level <= debugPrint.level:
        FreeCAD.Console.PrintMessage(msg + '\n')
debugPrint.level = 4 if hasattr(os,'uname') and os.uname()[1].startswith('antoine') else 2

def formatDictionary( d, indent):
    return '%s{' % indent + '\n'.join(['%s%s:%s' % (indent,k,d[k]) for k in sorted(d.keys())]) + '}'

class ConstraintSelectionObserver:
     def __init__(self, selectionGate, parseSelectionFunction, 
                  taskDialog_title, taskDialog_iconPath, taskDialog_text,
                  secondSelectionGate=None):
          self.selections = []
          self.parseSelectionFunction = parseSelectionFunction
          self.secondSelectionGate = secondSelectionGate
          FreeCADGui.Selection.addObserver(self)  
          FreeCADGui.Selection.removeSelectionGate()
          FreeCADGui.Selection.addSelectionGate( selectionGate )
          wb_globals['selectionObserver'] = self
          self.taskDialog = SelectionTaskDialog(taskDialog_title, taskDialog_iconPath, taskDialog_text)
          FreeCADGui.Control.showDialog( self.taskDialog )
     def addSelection( self, docName, objName, sub, pnt ):
         debugPrint(4,'addSelection: docName,objName,sub = %s,%s,%s' % (docName, objName, sub))
         obj = FreeCAD.ActiveDocument.getObject(objName)
         self.selections.append( SelectionRecord( docName, objName, sub ))
         if len(self.selections) == 2:
             self.stopSelectionObservation()
             self.parseSelectionFunction( self.selections)
         elif self.secondSelectionGate <> None and len(self.selections) == 1:
             FreeCADGui.Selection.removeSelectionGate()
             FreeCADGui.Selection.addSelectionGate( self.secondSelectionGate )
     def stopSelectionObservation(self):
         FreeCADGui.Selection.removeObserver(self) 
         del wb_globals['selectionObserver']
         FreeCADGui.Selection.removeSelectionGate()
         FreeCADGui.Control.closeDialog()


class SelectionRecord:
    def __init__(self, docName, objName, sub):
        self.Document = FreeCAD.getDocument(docName)
        self.ObjectName = objName
        self.Object = self.Document.getObject(objName)
        self.SubElementNames = [sub]


class SelectionTaskDialog:
    def __init__(self, title, iconPath, textLines ):
        self.form = SelectionTaskDialogForm( textLines )
        self.form.setWindowTitle( title )    
        if iconPath <> None:
            self.form.setWindowIcon( QtGui.QIcon( iconPath ) )
    def reject(self):
        wb_globals['selectionObserver'].stopSelectionObservation()
    def getStandardButtons(self): #http://forum.freecadweb.org/viewtopic.php?f=10&t=11801
        return 0x00400000 #cancel button
class SelectionTaskDialogForm(QtGui.QWidget):    
    def __init__(self, textLines ):
        super(SelectionTaskDialogForm, self).__init__()
        self.textLines = textLines 
        self.initUI()
    def initUI(self):
        vbox = QtGui.QVBoxLayout()
        for line in self.textLines.split('\n'):
            vbox.addWidget( QtGui.QLabel(line) )
        self.setLayout(vbox)


def findUnusedObjectName(base, counterStart=1, fmt='%02i'):
    i = counterStart
    objName = '%s%s' % (base, fmt%i)
    usedNames = [ obj.Name for obj in FreeCAD.ActiveDocument.Objects ]
    while objName in usedNames:
        i = i + 1
        objName = '%s%s' % (base, fmt%i)
    return objName

def findUnusedLabel(base, counterStart=1, fmt='%02i'):
    i = counterStart
    label = '%s%s' % (base, fmt%i)
    usedLabels = [ obj.Label for obj in FreeCAD.ActiveDocument.Objects ]
    while label in usedLabels:
        i = i + 1
        label = '%s%s' % (base, fmt%i)
    return label

class ConstraintObjectProxy:
    def execute(self, obj):
        self.callSolveConstraints()
        obj.touch()
    def callSolveConstraints(self):
        from assembly2solver import solveConstraints
        solveConstraints( FreeCAD.ActiveDocument )

class ImportedPartViewProviderProxy:
    def onDelete(self, feature, subelements): # subelements is a tuple of strings
        viewObject = feature
        obj = viewObject.Object
        doc = obj.Document
        debugPrint(2, 'ConstraintObjectViewProviderProxy.onDelete: removing constraints refering to %s (label:%s)' % (obj.Name, obj.Label))
        deleteList = []
        for c in doc.Objects:
            if 'ConstraintInfo' in c.Content:
                if obj.Name in [ c.Object1, c.Object2 ]:
                    deleteList.append(c)
        if len(deleteList) > 0:
            debugPrint(3, "  delete list %s" % str(deleteList) )
            for c in deleteList:
                debugPrint(2, "  - removing constraint %s" % c.Name )
                doc.removeObject(c.Name)
        return True # If False is returned the object won't be deleted

class SelectConstraintObjectsCommand:
    def Activated(self):
        constraintObj = FreeCADGui.Selection.getSelectionEx()[0].Object
        obj1Name = constraintObj.Object1
        obj2Name = constraintObj.Object2
        FreeCADGui.Selection.addSelection( FreeCAD.ActiveDocument.getObject(obj1Name) )
        FreeCADGui.Selection.addSelection( FreeCAD.ActiveDocument.getObject(obj2Name) )
    def GetResources(self): 
        return { 'MenuText': 'Select Objects' } 
FreeCADGui.addCommand('selectConstraintObjects', SelectConstraintObjectsCommand())

def printSelection(selection):
    entries = []
    for s in selection:
        for e in s.SubElementNames:
            entries.append(' - %s:%s' % (s.ObjectName, e))
            if e.startswith('Face'):
                ind = int( e[4:]) -1 
                face = s.Object.Shape.Faces[ind]
                entries[-1] = entries[-1] + ' %s' % str(face.Surface)
    return '\n'.join( entries[:5] )
                


def updateOldStyleConstraintProperties( doc ):
    'used to update old constraint attributes, [object, faceInd] -> [object, subElement]...'
    for obj in doc.Objects:
        if 'ConstraintInfo' in obj.Content:
            updateObjectProperties( obj )

def updateObjectProperties( c ):
    if hasattr(c,'FaceInd1'):
        debugPrint(3,'updating properties of %s' % c.Name )
        for i in [1,2]:
            c.addProperty('App::PropertyString','SubElement%i'%i,'ConstraintInfo')
            setattr(c,'SubElement%i'%i,'Face%i'%(getattr(c,'FaceInd%i'%i)+1))
            c.setEditorMode('SubElement%i'%i, 1) 
            c.removeProperty('FaceInd%i'%i)
        if hasattr(c,'planeOffset'):
            v = c.planeOffset
            c.removeProperty('planeOffset')
            c.addProperty('App::PropertyDistance','offset',"ConstraintInfo")
            c.offset = '%f mm' % v
        if hasattr(c,'degrees'):
            v = c.degrees
            c.removeProperty('degrees')
            c.addProperty("App::PropertyAngle","angle","ConstraintInfo")
            c.angle = v
    elif hasattr(c,'EdgeInd1'):
        debugPrint(3,'updating properties of %s' % c.Name )
        for i in [1,2]:
            c.addProperty('App::PropertyString','SubElement%i'%i,'ConstraintInfo')
            setattr(c,'SubElement%i'%i,'Edge%i'%(getattr(c,'EdgeInd%i'%i)+1))
            c.setEditorMode('SubElement%i'%i, 1) 
            c.removeProperty('EdgeInd%i'%i)
        v = c.offset
        c.removeProperty('offset')
        c.addProperty('App::PropertyDistance','offset',"ConstraintInfo")
        c.offset = '%f mm' % v
    if c.Type == 'axial' or c.Type == 'circularEdge':
        if not hasattr(c, 'lockRotation'):
            debugPrint(3,'updating properties of %s, to add lockRotation (default=false)' % c.Name )
            c.addProperty("App::PropertyBool","lockRotation","ConstraintInfo")
    
def getObjectFaceFromName( obj, faceName ):
    assert faceName.startswith('Face')
    ind = int( faceName[4:]) -1 
    return obj.Shape.Faces[ind]

def planeSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        subElement = selection.SubElementNames[0]
        if subElement.startswith('Face'):
            face = getObjectFaceFromName( selection.Object, subElement)
            return str(face.Surface) == '<Plane object>'
    return False

def cylindricalPlaneSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        subElement = selection.SubElementNames[0]
        if subElement.startswith('Face'):
            face = getObjectFaceFromName( selection.Object, subElement)
            return hasattr(face.Surface,'Radius')
    return False

def getObjectEdgeFromName( obj, name ):
    assert name.startswith('Edge')
    ind = int( name[4:]) -1 
    return obj.Shape.Edges[ind]

def CircularEdgeSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        subElement = selection.SubElementNames[0]
        if subElement.startswith('Edge'):
            edge = getObjectEdgeFromName( selection.Object, subElement)
            return hasattr( edge.Curve, 'Radius' )
    return False

def LinearEdgeSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        subElement = selection.SubElementNames[0]
        if subElement.startswith('Edge'):
            edge = getObjectEdgeFromName( selection.Object, subElement)
            return isinstance(edge.Curve, Part.Line)
    return False

def vertexSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        return selection.SubElementNames[0].startswith('Vertex')
    return False

def getObjectVertexFromName( obj, name ):
    assert name.startswith('Vertex')
    ind = int( name[6:]) -1 
    return obj.Shape.Vertexes[ind]

def sphericalSurfaceSelected( selection ):
    if len( selection.SubElementNames ) == 1:
        subElement = selection.SubElementNames[0]
        if subElement.startswith('Face'):
            face = getObjectFaceFromName( selection.Object, subElement)
            return str( face.Surface ).startswith('Sphere ')
    return False




